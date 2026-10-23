# WP-051-02K (continuación) — recuperación de capacidad con autorización limitada

**Paquete:** WP-051-02K · **Generado:** 2026-10-23T19:08:52Z · **Dictamen:** `BLOCKED`

## Espacio

| Momento | Libre | Presupuesto | Margen | Instrumentos |
| --- | --- | --- | --- | --- |
| Antes | 18.3069 GiB | 14.564 GiB | 3.7429 GiB | coinciden |
| Después | 19.3952 GiB | 14.564 GiB | 4.8312 GiB | coinciden |

Presupuesto: `FROZEN_02J_P90` — 02J p90 drawdown 12.467 GiB + 2 GiB protection floor + 0.0972 GiB campaign growth over the 90-day window; frozen because the store that produced it is absent in this tree

## Limpieza

| Objetivo | Planificado | Recuperado | Ficheros | Omitidos |
| --- | --- | --- | --- | --- |
| playwright-obsolete | 702.0 MiB | 702.0 MiB | 602 | 0 |
| temp-stale | 293.5 MiB | 245.5 MiB | 115 | 7 |

Total recuperado: **0.9253 GiB**; el volumen se movió 1114.4 MiB en el mismo tramo (la diferencia es ruido del host, no un fallo del borrado).

### No tocado, y por qué

| Ruta | Bytes | Motivo |
| --- | --- | --- |
| `C:\Users\GVLLFR0035\AppData\Local\hermes` | 2049.5 MiB | el propietario no autorizó este árbol |
| `C:\Users\GVLLFR0035\Downloads\bot_crypto_004g` | 0.0 MiB | el propietario no autorizó este worktree |
| `C:\Users\GVLLFR0035\.cache\codex-runtimes` | 1329.7 MiB | runtime of a tool that is running (codex-computer-use-swift.exe#28092, codex-windows-sandbox-service.exe#38040, codex.exe#14028): regenerable, but not provably unused, so not deleted |

## Crecimiento observado

120 s de muestreo; caída acumulada 5118.4 MiB, explicada por contadores de escritura en un 86.99 %.

| Proceso | Escrito | Intervalos |
| --- | --- | --- |
| `SearchIndexer.exe` | 4352.8 MiB | 16 |
| `bun.exe` | 65.8 MiB | 11 |
| `chrome.exe` | 14.2 MiB | 39 |
| `msedge.exe` | 11.2 MiB | 13 |
| `System` | 5.0 MiB | 14 |
| `ChatGPT.exe` | 2.3 MiB | 11 |

> write counters are per process and cumulative; a large writer is not necessarily the one that lowered free space, so drops and writes are reported side by side. Deferred allocation (paging, compression, delayed writes) can move the volume after the write.

## Integridad

| Comprobación | Estado | Detalle |
| --- | --- | --- |
| EXPERIMENT_FILES_IDENTICAL | PASS | 14 files hashed either side; 0 differ |
| RECOVERED_RECORD_MATCHES_COMMIT | PASS | 12 files recovered from 9983b050; 0 differ from their blob |
| LIVE_EXPERIMENT_PRESENT | FAIL | absent from this checkout: capture_runner, contract, observer_watchdog, store; the record was recovered from Git, the live artefacts were not |
| STORE_PRESENT | FAIL | campaign store absent at C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04: continuity cannot be certified from this tree |

## Guard

Estado: `ABSENT_IN_THIS_TREE`. Script presente: False; proceso en marcha: False; store presente: False.

> the guard shipped with the 02J/02K worktree, which is not in this tree; nothing here claims the campaign is protected while both the guard and the store it guards are absent

## Bloqueos

- `CAMPAIGN_STORE_ABSENT`
- `EXPERIMENT_ARTIFACTS_ABSENT`

## Próxima acción

Restaurar el store de la campaña antes de hablar de continuidad: sin él no hay filas que proteger ni guard que medir.
