# WP-051-02K (continuación) — recuperación de capacidad con autorización limitada

**Paquete:** WP-051-02K · **Generado:** 2026-10-23T19:01:25Z · **Dictamen:** `BLOCKED`

## Espacio

| Momento | Libre | Presupuesto | Margen | Instrumentos |
| --- | --- | --- | --- | --- |
| Antes | 18.6116 GiB | 14.564 GiB | 4.0476 GiB | coinciden |
| Después | 18.8172 GiB | 14.564 GiB | 4.2532 GiB | coinciden |

Presupuesto: `FROZEN_02J_P90` — 02J p90 drawdown 12.467 GiB + 2 GiB protection floor + 0.0972 GiB campaign growth over the 90-day window; frozen because the store that produced it is absent in this tree

## Limpieza

| Objetivo | Planificado | Recuperado | Ficheros | Omitidos |
| --- | --- | --- | --- | --- |

Total recuperado: **0.0 GiB**; el volumen se movió 210.6 MiB en el mismo tramo (la diferencia es ruido del host, no un fallo del borrado).

## Crecimiento observado

60 s de muestreo; caída acumulada 11.4 MiB, explicada por contadores de escritura en un 370.36 %.

| Proceso | Escrito | Intervalos |
| --- | --- | --- |
| `bun.exe` | 19.2 MiB | 3 |
| `SearchIndexer.exe` | 10.5 MiB | 3 |
| `msedge.exe` | 5.7 MiB | 8 |
| `chrome.exe` | 3.1 MiB | 20 |
| `System` | 1.6 MiB | 8 |
| `ChatGPT.exe` | 1.2 MiB | 5 |

> write counters are per process and cumulative; a large writer is not necessarily the one that lowered free space, so drops and writes are reported side by side. Deferred allocation (paging, compression, delayed writes) can move the volume after the write.

## Integridad

| Comprobación | Estado | Detalle |
| --- | --- | --- |
| EXPERIMENT_FILES_IDENTICAL | PASS | 196 files hashed either side; 0 differ |
| RECOVERED_RECORD_MATCHES_COMMIT | PASS | 12 files recovered from 9983b050; 0 differ from their blob |
| LIVE_EXPERIMENT_PRESENT | FAIL | absent from this checkout: store; the record was recovered from Git, the live artefacts were not |
| STORE_PRESENT | FAIL | campaign store absent at C:\Users\GVLLFR0035\Downloads\exp004a-recovery-02k\data\forward\edge04: continuity cannot be certified from this tree |

## Guard

Estado: `FILE_PRESENT_NO_PROCESS`. Script presente: True; proceso en marcha: False; store presente: False.

> the guard shipped with the 02J/02K worktree, which is not in this tree; nothing here claims the campaign is protected while both the guard and the store it guards are absent

## Bloqueos

- `CAMPAIGN_STORE_ABSENT`

## Próxima acción

Restaurar el store de la campaña antes de hablar de continuidad: sin él no hay filas que proteger ni guard que medir.
