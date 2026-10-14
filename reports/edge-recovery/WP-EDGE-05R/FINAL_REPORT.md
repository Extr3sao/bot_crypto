# WP-EDGE-05R — Recuperación y coherencia de informes: informe ejecutivo

*Una sola lectura, tomada a las `2026-10-14T06:57:22Z` (`EDGE05R-READ-20261014T065722Z`, digest `eb91c3e2ad584861…`). Todas las cifras de este informe llevan su instante de lectura y el digest del artefacto del que salen; los tres informes —este, el técnico y el JSON— son tres lecturas del mismo fichero congelado.*

## 1. Estado en una línea

**Veredicto del work package: `CLOSED_WITH_OPEN_ITEMS`** — todas las filas que se podían medir están en PASS, con 2 declaradas no probadas: ACC-08, ACC-14.

**Estado de la ingesta: `INGEST_RESUMED`** — La lane rechazó 35 tick(s) por disco y ha vuelto a observar después: el rechazo fue real y ha terminado.

## 2. Disco: qué estaba mal, qué se devolvió y qué no se tocó

- El volumen tenía **4.013 GiB libres** al tomar esta lectura (`ABOVE_CRITICAL_BELOW_HEALTHY`). El repositorio ocupa 5724066394 bytes; el resto del volumen está fuera de este workstream y no se ha medido ni tocado.
- Se recuperaron **45461012 bytes** de cachés de herramienta (`__pycache__`, mypy, pytest, ruff, hypothesis, coverage): cada ruta se comprobó en el momento de borrarla como caché por nombre, no versionada por git y nombrada en `.gitignore` — la base de ejemplos de `hypothesis` solo entra en la regla desde que el `.gitignore` la nombra. La barrida registró `HEALTHY` en su propio instante (`5907402752` bytes libres), que no es el instante de esta lectura.
- El volumen está **por encima del suelo crítico y por debajo del sano** (`ABOVE_CRITICAL_BELOW_HEALTHY`, 4.013 GiB libres al tomar esta lectura): la lane ingiere y la publicación pesada espera, y un consumidor más cierra la ventana. El suelo que falta no lo puede cerrar este repositorio — su parte está en `STORAGE_INVENTORY.md` y en el plan adjunto, no ejecutado aquí.
- Nada de datos de mercado, evidencia, otros workstreams, código ni el entorno se tocó: el criterio de cada ruta borrada se re-verificó en el momento de borrarla.
- El plan que **sí** requeriría una decisión del propietario —los consumidores del volumen fuera del repositorio y su tamaño— está en `STORAGE_INVENTORY.md` y en el plan adjunto, no ejecutado aquí.

## 3. La lane, después del rechazo

- La lane rechazó **35 tick(s)** por disco, el primero a las `2026-10-13T20:25:56Z`, **antes de hacer ninguna petición de mercado** y sin borrar nada.
- El tick programado **después** de la recuperación volvió a observar: `OBSERVED` a las `2026-10-14T06:57:08Z` con 3 barra(s) nuevas, y sin que nadie ejecutara el comando a mano. Es la comprobación que pedía el encargo: el mismo planificador, con el volumen por encima del suelo, y el rechazo anterior conservado en el registro.
- Total: **41 ticks observados** de 85, 18318 barras en 6 series, 43 slots sellados.

## 4. Clasificación de fallos: la causa, no el sitio donde se notó

El vocabulario queda cerrado en seis causas y se comprueban: `RESOURCE_PRESSURE`, `PROVIDER_FAILURE`, `DATA_QUALITY_FAILURE`, `RUNTIME_FAILURE`, `SCHEDULER_FAILURE` y `EXPECTED_NO_NEW_DATA`. Un tick que la lane rechaza por disco se notifica por el código de resultado del planificador, pero **la causa es el volumen**: ahora se archiva como `RESOURCE_PRESSURE`, con alerta `TICK_REFUSED_RESOURCE`, y el planificador se declara explícitamente limpio en lugar de acusado. El verificador independiente recalcula esa regla desde el propio dato y la matriz de sabotajes incluye un caso que archiva un rechazo por recursos como fallo del planificador: si volviera a etiquetarse mal, ese sabotaje dejaría de detectarse y el self-test fallaría.

- Lectura más nueva (`2026-10-14T06:47:33Z`): `WATCH_DEGRADED` / `RESOURCE_PRESSURE` (esquema `EDGE05_WATCHDOG_V2`), **sin clase de fallo asignada**: lo que la categoría nombra es presión — un aviso del volumen, no un fallo del planificador ni de la lane.
- El mismo instante se publica ahora en las dos formas que se derivaron: `2026-10-14T06:55:53.0000000Z` como instante y `10/14/2026 08:55:53` como la grafía de la plataforma, y la sonda declara su propio retraso medido entre dos instantes que la misma comprobación publica (`watchdog_newest_probe_answer_lag_seconds` = 11.013 s). Antes, la grafía local viajaba bajo un nombre `_utc` — el mismo instante a dos horas de distancia dentro de una fila — y el desfase de reloj publicado era ese retraso con el signo cambiado.
- Lecturas: 53; alertas: 55.

## 5. Informes coherentes

Los tres informes se generan con **un solo comando** desde una instantánea inmutable (`READING_SNAPSHOT.json`) que lleva su propio digest y **105 cifras**, cada una con `run_id`, `as_of_utc`, `source_artifact`, `source_digest` y `measurement_scope`, procedentes de 18 artefactos de origen con su digest. Si la instantánea se edita después de tomarla, el generador **se niega a renderizar** y sale con código distinto de cero. Ya no hay cifras escritas a mano que puedan quedar obsoletas: es el defecto que obligó a corregir dos veces los informes de WP-EDGE-05.

## 6. Matriz de aceptación

**2 NOT_TESTED, 13 PASS.** Ninguna fila se declara por afirmación: cada una cita las cifras que la sostienen.

| ACC | Qué se exigía | Resultado | Cifras que lo sostienen |
| --- | --- | --- | --- |
| ACC-01 | Runtime audit and a reproducible baseline | **PASS** | `runtime_authority_map_bytes`, `git_head` |
| ACC-02 | The scheduler really fires, with nobody running the command | **PASS** | `lane_ticks_observed`, `lane_ticks_total`, `watchdog_newest_at_utc` |
| ACC-03 | The watchdog detects an induced stop, with a measured latency | **PASS** | `watchdog_detection_latency_seconds`, `watchdog_alert_kinds` |
| ACC-04 | A stop after partial persistence duplicates no bar | **PASS** | `defect_chain_broken`, `defect_double_claim`, `restart_proof_broken`, `reconciliation_seals_orphaned` |
| ACC-05 | A stop during decision or seal leaves one logical decision per slot | **PASS** | `defect_seal_missing`, `defect_seal_orphaned`, `defect_decision_divergence`, `reconciliation_seals` |
| ACC-06 | A retry of the same slot is idempotent everywhere | **PASS** | `lane_ticks_already_observed`, `lane_ticks_already_running` |
| ACC-07 | A restart leaves no orphan lease and no crash | **PASS** | `restart_proof_broken`, `reconciliation_unattributed_bars`, `watchdog_newest_at_utc` |
| ACC-08 | A provider outage is classified, and no forward day is invented | **NOT_TESTED** | `defect_chain_broken` |
| ACC-09 | Disk pressure blocks before corruption and preserves evidence | **PASS** | `lane_ticks_disk_budget_exceeded`, `lane_first_disk_refusal_utc`, `volume_verdict`, `storage_reclaimed_bytes`, `storage_verdict_after` |
| ACC-10 | Forward eligibility excludes backfill and incomplete days | **PASS** | `forward_days_with_data`, `forward_days_densely_covered_but_backfilled`, `forward_days_prospectively_observed`, `forward_days_required` |
| ACC-11 | Risk limits and gates are unchanged | **PASS** | `lane_last_parity_verdict`, `lane_last_ruleset_params_hash` |
| ACC-12 | Independent verification, with the command's own exit code | **PASS** | `verification_verdict`, `verification_self_test`, `tests_chain_passed`, `tests_chain_exit_code`, `tests_chain_failed` |
| ACC-13 | Operation without orders | **PASS** | `lane_rows_claiming_an_order`, `watchdog_rows_claiming_an_order`, `reconciliation_market_requests` |
| ACC-14 | A long unattended window | **NOT_TESTED** | `forward_days_prospectively_observed`, `forward_days_required` |
| ACC-15 | Git and traceability | **PASS** | `git_head`, `git_commits_since_root`, `git_dirty_entries`, `github_push_state` |

## 7. Lo que este work package NO declara

- No se declara `CERTIFIED`, `READY_FOR_PAPER` ni `PRODUCTION_READY`.
- **0 de 60 días forward válidos.** El gate de 60 días sigue abierto y este encargo no acorta uno solo de sus días.
- No se ha tocado sizing, límites de riesgo, estrategias, señales ni gates de promoción.
- No se ha enviado ninguna orden: 0 en el registro de la lane, 0 en el del vigilante, 0 en la reconciliación.
- La publicación en GitHub **está disponible y no se ha ejercido** (`AVAILABLE_NOT_EXERCISED`, sonda con código `0`): ningún ref remoto se ha tocado y los commits quedan locales hasta que el operador lo pida.
