# WP-051-02K (operativo) — RUN REPORT

**Paquete:** WP051-02K Operational Unblock · **Generado:** 2026-10-24T07:30Z · **Dictamen:** `BLOCKED_WITH_EVIDENCE`

Cada paso de abajo se ejecutó en esta sesión; los códigos de salida son los del proceso, no los de un filtro. La evidencia derivada vive junto a este fichero (`EVIDENCE.json`, `CAPACITY_MEASUREMENT.json`, `GUARD_VERIFICATION.json`, `VERIFIER_02K.stdout.txt`, `VERIFIER_EDGE04.json`), y las entradas crudas de las que se construyó —las dos búsquedas en disco y los dos informes del fetcher de corpus— están en `raw/`.

| # | WP | Acción | Salida | Resultado |
|---|---|---|---|---|
| S01 | 02 | 12 muestras de espacio contra el presupuesto congelado | 0 | `CAPACITY_OK` |
| S02 | 01 | Repuntar las dos tareas programadas al guard recuperado | 0 | `CHANGED` (0 tareas creadas) |
| S03 | 01 | Guard contra un `state root` inexistente | 1 → **2** | defecto reparado |
| S04 | 01 | Seis casos de inyección de fallos | 0 | `GUARD_OPERATIONAL` 6/6 |
| S05 | 01 | `schtasks /run` de watchdog y alarma | 0 | `LastTaskResult` 0 y 0 |
| S06 | 03 | Re-derivar el corpus 1h y contrastarlo con el pin | 0 | `RESTORED_AND_PINNED` 3/3 |
| S07 | 03 | Resolver el shard 15m por sus bytes publicados | 1 | `NOT_REPRODUCIBLE` 0/3 |
| S08 | 03 | Buscar los shards 15m en `C:` y `G:` | 0 | `ABSENT` |
| S09 | 03 | Llamar al pin congelado | 3 | `PIN_REFUSES` |
| S10 | 03 | Primer tick de la identidad nueva | 1 | `RUNTIME_EXCEPTION` |
| S11 | 04 | Verificador sellado 02K | 1 | 11/18 PASS |
| S12 | 04 | Verificador de la lane sobre la raíz nueva | 1 | 7/15 `VERIFY_FAIL` |
| S13 | 05 | Commit del arreglo del guard, solo ese fichero | 0 | `0e41566d` |

## S01 — capacidad

Presupuesto congelado `15 638 712 264 B` (14.5647 GiB), leído de `wp051_02j/CAPACITY_PLAN.json#required.at_p90_bytes` y **no** recalculado. Doce muestras cada 20 s (220 s):

| Métrica | Valor |
|---|---|
| Libre mínimo | 39.3457 GiB |
| Libre mediano | 40.6635 GiB |
| Peor margen sobre el presupuesto | **+24.781 GiB** |
| Peor caída observada entre muestras | 0.4703 GiB |
| Cambio neto en la ventana | −1.4581 GiB |

Borrados: **ninguno**. El volumen ya superaba el presupuesto antes de tocar nada, y borrar evidencia o el árbol de otro agente habría costado más que el problema que este paquete viene a reparar. Lo único reclamable identificado son cachés derivadas (0.1153 GiB de `__pycache__`/`.mypy_cache`/`.pytest_cache` en los tres árboles) y no se han tocado.

## S02/S05 — guard y planificador

Antes: ambas tareas apuntaban a `bot-freebuff-exp004a-02h\scripts\edge04_watchdog.py`, un fichero borrado; último resultado `2`, es decir, un intérprete que no encontraba el script. Ahora:

| Tarea | Cadencia | Acción | Último resultado |
|---|---|---|---|
| `TradingAgentic-EDGE04-Watchdog` | 15 min | `<venv> edge04_watchdog.py --state-root …/edge04r01` | **0** |
| `TradingAgentic-EDGE04-Alarm` | 10 min | ídem `--supervise` | **0** |

Se han **cambiado** las dos acciones existentes; no se ha creado ninguna tarea, así que no hay monitores duplicados. Las dos siguen en modo interactivo, `LIMITED`, con los mismos umbrales (aviso 5 GiB, crítico 2 GiB, silencio ×3).

Transición observada en el planificador real: `UNREADABLE → RECOVERED → OK`, con `SUPERVISOR.json` en `WATCHDOG_ALIVE` y una antigüedad del watchdog de 19 s.

## S03/S04 — el defecto del guard

`disk_reading()` llamaba a `shutil.disk_usage(state_root)` sobre una ruta que puede no existir. Con la raíz ausente —el caso exacto para el que existe un watchdog— el proceso moría con `FileNotFoundError` y **nunca** llegaba a su propio `UNREADABLE`, ni al código de salida 2, ni al fichero de atención. Se mide el ancestro existente más cercano y se declara `path_exists: false`; umbrales y política, intactos.

Seis casos, todos con el par (estado, código) documentado:

| Caso | Estado | Salida | Nota |
|---|---|---|---|
| Raíz inexistente | `UNREADABLE` | 2 | marcador `ATTENTION_REQUIRED.txt` levantado |
| Tick fresco | `OK` | 0 | |
| Observador callado 70 min | `STALE` | 9 | |
| Ticks rechazados por espacio | `BLOCKED` | 8 | **recibo real del toast** (`receipt: true`) |
| Recuperación posterior | `RECOVERED` | 0 | marcador retirado |
| Líneas ilegibles en el log | `DEGRADED` | 1 | |

No cubierto: las ramas `WARNING`/`CRITICAL`, que exigirían llevar el volumen bajo sus suelos.

## S06/S07 — corpus congelado

El pin no es opcional: `run_forward_observation` llama a `assert_frozen_corpus()` antes de pedir una sola barra.

**1h — restaurado y demostrado.** El mismo endpoint, la misma serialización y el mismo rango que el productor que sigue en el repo (`scripts/fetch_alpha_expansion_history.py`) reproducen el corpus **byte a byte**:

| Activo | Barras | Digest | Pin | |
|---|---|---|---|---|
| BTC | 62 724 | `f4d16c3664c142d1…` | `f4d16c3664c142d1` | ✅ |
| ETH | 62 724 | `365046d4738aa7b1…` | `365046d4738aa7b1` | ✅ |
| SOL | 48 646 | `847d8eb45eafebd8…` | `847d8eb45eafebd8` | ✅ |

23 shards, 19 380 640 B. Aceptados por el pin, no por este informe.

**15m — no reproducible.** No queda en el árbol ningún productor de este shard, así que no hay normalización que reproducir; se probó la única que sí reproduce el 1h, resolviendo la ventana por longitud de bytes en vez de adivinar una fecha:

| Activo | Barras | Bytes | Publicado | Faltan | sha256 |
|---|---|---|---|---|---|
| BTC | 38 994 | 4 497 772 | 4 497 888 | 116 B | ≠ |
| ETH | 40 152 | 4 466 430 | 4 466 466 | 36 B | ≠ |
| SOL | 40 095 | 4 222 969 | 4 223 041 | 72 B | ≠ |

La diferencia es menor que una barra en los tres casos, y el sha256 no coincide: la ventana original no es alcanzable con este normalizador. Buscados los ficheros en todo `C:` (27 coincidencias de nombre, **0** de `*_15m.json`) y en `G:` (0), incluida la papelera y `incident-backup-20261023`. No se sustituyen por una reconstrucción: un shard fabricado para encajar un hash es exactamente lo que el encargo prohíbe.

## S09/S10 — ejecución nueva, identidad nueva

| | |
|---|---|
| `state_root` | `data/forward/edge04r01` |
| `store_root` | `data/forward/edge03r01` |
| `run_id` | `FWD-EDGE04-20261024T071500Z` (derivado del slot nuevo) |
| Resultado | `RUNTIME_EXCEPTION`, salida 1, `FileNotFoundError` |
| Duración | 21.7 s (2 intentos) |
| Filas persistidas | 2 · corruptas 0 · lease liberado |

La identidad perdida (`data/forward/edge04`) no se reutiliza. El almacén nuevo es persistente, verificable y reanudable —el mismo slot reentra con el mismo `run_id` sin perder filas— pero **no contiene ninguna observación**, porque el pin se niega antes de la primera petición de mercado.

## S11/S12 — verificación independiente

| Verificador | Salida | Resultado |
|---|---|---|
| `scripts/exp004a_wp051_02k_verify.py` (sellado) | 1 | 11/18 PASS, 7 FAIL |
| `scripts/edge04_verify.py` (sellado) | 1 | 7/15, `VERIFY_FAIL` |

`BUILDER != VERIFIER`: los verificadores son código sellado en `9983b050`; el constructor es el tick, el fetcher de corpus y el arnés del guard. El colector de evidencia es herramienta de constructor y lo declara.

Los 7 fallos del verificador 02K no son regresiones nuevas: cuatro son el almacén ausente (`WRITE_ONCE_SHARDS_UNCHANGED`, `APPEND_ONLY_PREFIXES_INTACT`, `NO_ROW_LOST_OR_INVENTED`, `FLOOR_UNCHANGED`), dos son cifras de capacidad de 02K que el host ha desmentido al aflojarse (`VOLUME_IS_AT_LEAST_AS_TIGHT_AS_REPORTED`, `BUDGET_RECOMPUTED_FROM_THE_LOG`) y uno es la limpieza que 02K sí hizo (`NOTHING_FOREIGN_WAS_DELETED`, 209 directorios, todos dentro de la familia del repositorio).

## Pruebas

| Suite | Resultado | Lectura |
|---|---|---|
| Arnés del guard | 6/6 | |
| `test_edge04_autonomous.py` | 5 fallos, 44 pasan | **idénticos** con el guard revertido a `9983b050`: no es el arreglo, es la lane sin corpus |
| `02h` + `02i` + `02j` | 1 fallo, 62 pasan | `COVERAGE_CEILING` 6408 vs 6456, también con el guard revertido |
| `test_edge04r_continuity.py` + `02k_continue` | incluidos en 104 pasan | |
| pytest del verificador 02K | 32 pasan, salida 0 | |

`TEST_RESULT != CAMPAIGN_READINESS`: ninguna de estas cifras dice que la campaña pueda observarse.
